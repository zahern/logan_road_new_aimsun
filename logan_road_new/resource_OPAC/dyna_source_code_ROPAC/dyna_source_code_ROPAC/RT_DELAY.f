      subroutine RT_DELAY(n1,n2,Nosco,nf,narcs,nodenumber,lll)
c	  ,Kqueue,matrixgreen,mgreen,
c     + matrixvehicle2,
c     + nsign,noofnodes,nu_mv,SatFlowRate,tii)

      use muc_mod

      integer error,n1,n2,Nosco,narcs,nf,j2,jd,id,i,g,h
      integer lll,phase2	  
c	  integer nu_mv,noofnodes,phase,	  
      real delcont,veh_stoped,lefsat
c       real  ,tii	  
      real,allocatable::delaya(:,:)
c      real,DIMENSION(1:7,100)::matrixvehicle3
 
c      integer matrixgreen(n2-n1+1,Nosco)
c      integer mgreen(n2-n1+1,Nosco),Kqueue(narcs,7) 	
c      integer matrixvehicle2(nf,Nosco+1,narcs)
c      integer nsign(noofnodes*nu_mv,14)
c      real SatFlowRate(narcs)	  
c      matrixvehicle3(:,:)=0
      veh_stoped=0	  
c      print *,'Alex_RT_DELAY_init'			  
	  
      allocate(delaya(narcs,7),stat=error)
      if(error.ne.0) then
      write(911,*) 'allocate delaya error - insufficient memory'
      stop
      endif
      delaya(:,:)=0
	  

      contveh_que2=contveh_que
      matrixvehicle2=matrixvehicle1	  
      delaycont=0	  
c      if(nodenumber.eq.5) print *,'Alex_RT_DELAY_init',1	

      do jd=1,Nosco						   ! all intervals
	  
      do id=n1,n2							   ! all phases
       phase2=nsign(id,1)
       do j2=6,nsign(id,5)+5	               ! to all upstream nodes
             i=nsign(id,j2)        			   ! Upstream nodes of the inbound links
			 
          IF(nf.lt.phase2.or.Nosco+1.lt.jd.or.narcs.lt.i
     +  .or.phase2.eq.0.or.jd.eq.0.or.i.eq.0)THEN
            print *,'Alexproblem5',phase2,jd,i
               stop
          ENDIF
       
c       veh_stoped=matrixvehicle2(phase2,jd,i)-SatFlowRate(i)
c     + *tii*60*matrixgreen(phase2,jd)
	 
c       matrixvehicle3(phase2,jd)=matrixvehicle3(phase2,jd)+
c     + matrixvehicle2(phase2,jd,i)	  

c      if(veh_stoped.gt.0)then

c        delaya(i,phase2)=delaya(i,phase2)+veh_stoped*(Nosco-jd+1)	  
c        delaya(i,phase2)=delaya(i,phase2)+veh_stoped
			  
c      endif

	  
       delaya(i,phase2)=delaya(i,phase2)
     + +contveh_que2(1,phase2,i)
     + +matrixvehicle2(phase2,jd,i)	 
     + -SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd)) 

	 
       if(delaya(i,phase2).lt.0) delaya(i,phase2)=0
       delaycont=delaycont+delaya(i,phase2)


		
      lefsat=SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd))

	  
      if(contveh_que2(1,phase2,i).gt.0)then	 
	  
        if(contveh_que2(1,phase2,i).ge.
     +		SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd)))then	       

        contveh_que2(1,phase2,i)=contveh_que2(1,phase2,i)
     + -SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd)) 
	 
        else
         if(SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd)).gt.0)then
		 
            lefsat=SatFlowRate(i)*tii*60*real(matrixgreen(phase2,jd))-
     +      contveh_que2(1,phase2,i)			
            contveh_que2(1,phase2,i)=0
			
         endif		 
	 
        endif
		
      endif

	  
      if(matrixvehicle2(phase2,jd,i).gt.0)then	 
	  
        if(matrixvehicle2(phase2,jd,i).ge.lefsat)then	       

        matrixvehicle2(phase2,jd,i)=matrixvehicle2(phase2,jd,i)-lefsat 
	 
        else
         if(lefsat.gt.0)then
			
            matrixvehicle2(phase2,jd,i)=0
			
         endif		 
	 
        endif
		
      endif
	  	  
	  
c        if(nodenumber.eq.120.and.veh_stoped.gt.0)then		  

c        print *,matrixvehicle2(phase2,jd,i),SatFlowRate(i)
c     + *tii*60*real(matrixgreen(phase2,jd)),matrixgreen(phase2,jd),
c     + jd,phase2,i,veh_stoped,delaya(i,phase2),delaycont	 
	 
c     	 endif
		
        enddo

       enddo

      enddo

	  
c      IF(nodenumber.eq.120)THEN
c        write(1,*) 'phase2 secuence',delaycont,mindelay
c        do g=1,nf
c         write(1,*) (matrixgreen(g,h), h=1, Nosco)
c        enddo		  
c      ENDIF

c        if(nodenumber.eq.120)then	
c          do j=1,nf
c           print *,(matrixgreen(j,i),i=1,Nosco),'*',
c     +		 (matrixvehicle3(j,i),i=1,Nosco)
c          enddo
c          print *,'delay=',delaycont
c          pause	   
c        endif

      if(delaycont.lt.mindelay)then
c       print *, 'transfer matrixgreen',delaycont,mindelay	  
       mindelay=delaycont
       mgreen=matrixgreen
c       matrixvehicle4=matrixvehicle3
       else
c       print *, 'DINOT transfer matrixgreen',delaycont,mindelay	   
      endif
			   
      deallocate(delaya)

c      print *,'Alex_RT_DELAY_end'			

      return
      end
