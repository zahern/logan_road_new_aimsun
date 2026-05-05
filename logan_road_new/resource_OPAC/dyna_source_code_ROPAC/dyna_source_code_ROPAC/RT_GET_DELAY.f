      subroutine RT_GET_DELAY(n1,n2,Nosco,nf,narcs,nodenumber)
c	  ,Kqueue,matrixvehicle2,
c     +	  contveh_que,nu_ph2)
	 
      use muc_mod
      use vector_mod
      use LinkList_mod
      use Intooi_mod
	  
      integer Itp1,i,nu,m,position,toto,narcs,Nosco,n1,n2,nu_ph2,nf
      integer phase2,j2,j,k,inode,mg,nll,limit	  
      logical Itp2
      real contveh_que_tmp 	
      j=0	  
c      integer Kqueue(narcs,7), contveh_que(2,nu_ph2,narcs)	  
c      integer matrixvehicle2(nf,Nosco+1,narcs)
	  
c	integer position
c      if(nodenumber.eq.5) print *,'Alex241a1'
	  
      do 6000 nu=n1,n2						  		! to all phases
       phase2=nsign(nu,1)	  
c      print *,'Alex241b'
	  
       do 7000 j2=6,nsign(nu,5)+5	             	! to all upstream nodes
        i=nsign(nu,j2)							 	! Upstream links 

c      print *,'Alex241c'
	  
      if(npar(i).gt.0)then 
       if(npar(i).gt.MaxLinkVeh)then
         print *, 'error' 
       endif
	   
c      print *,'Alex241da',i,phase2,Kqueue(i,phase2)
c      print *,'Alex241db',narcs,nu_ph2,Kqueue(i,phase2)
	 
c --
c -- this uniformly distributes vehicles in queue over the link . . .
c --	  
      if(nodenumber.eq.120)then
	  
c      print *,'in RT_GET_DELAY',i,nu,phase2

      endif

c -- loop over all vehicles on the link
 
c      print *,'Alex2411'
        p_mtxj_value=>LinkVehList(i)
c      print *,'Alex2412'
! -- This do while loop is to go through all the vehicle in the LinkVehList(i)
! -- move the vehicles and check if the vehicle reach the destinations
        do while(associated(p_mtxj_value%next_veh))
C	if(iteration.gt.0)print *, 'Alex000' 

         j=p_mtxj_value%veh    ! vehicle ID
										
         if(j.gt.0)then   
c		  if(mtxj(i,kj).gt.0) then

          Itp1=icurrnt(j)+1
          Itp2=.False.
          inode=nint(VhcAtt_Value(j,Itp1,1))
c	if(j.eq.42)then
c	if(iteration.gt.0.and.j.eq.213)print *,'Alex221-j=',j,inode,i,Itp1
c	endif
c      print *,'Alex2413'
	  
      do k=backpointr(inode),backpointr(inode+1)-1
c	if(iteration.gt.0.and.j.eq.213)print *,
c     +  'Alex222',idnod(i),UNodeOfBackLink(k),k
      	if(idnod(i).eq.UNodeOfBackLink(k))then
         nll=BackToForLink(k)
         Itp2=.True.
         exit
      	endif
      enddo
	  
c      print *,'Alex2414'
	  
             do 2222 m=6,5+nsign(nu,5)  ! to all upstream nodes
		      lnum=nsign(nu,m)
		      do 2222 mg=1,llink(lnum,nu_mv+1)
			  
c      if(nodenumber.eq.120)then
c        print *,'j=',j,'nll=',nll,'lnum=',lnum,'i=',i,
c     +	   movement(lnum,nu-n1+1,mg),llink(i,mg)
c        pause
c      endif	  			  
			  
                 if((movement(lnum,nu-n1+1,mg).eq.1).and.
     +			   ((lnum.eq.i).and.(llink(i,mg).eq.nll)))then
	 
     					IF(xpar(j).gt.0.0001)THEN
						
      position=nint(anint((xpar(j)-0.0001)/(v(i)/60)/(tii*60)))+1
c      position=nint(anint((xpar(j))/(vtmp(i)/60)/(tii*60)))+1
	  
      if(position.le.Nosco)then
						
          IF(nf.lt.phase2.or.Nosco+1.lt.position.or.narcs.lt.i)THEN
            print *,'Alexproblem4',phase2,position,i
               stop
          ENDIF							
						
        matrixvehicle2(phase2,position,i)=
     +  matrixvehicle2(phase2,position,i)+1

        matrixvehicle4(phase2,position)=matrixvehicle4(phase2,position)
     +  +matrixvehicle2(phase2,position,i)	
	 
c      else

c      print *,'vehicle no contado','phase=',phase2,'position=',
c     +	  position,i	  

      endif
	  
						ENDIF
						
                    exit	
					
                   endif

2222   continue
c      print *,'Alex2415'

        endif
		
        p_mtxj_value=>p_mtxj_value%next_veh
		
      enddo
	  
      endif
c      print *,'Alex2416'
7000  continue
c      print *,'Alex2417'
6000  continue


c      do jd=1,Nosco		
c       do nu=n1,n2						  		! to all phases
c          phase2=nsign(nu,1)	  
c        do j2=6,nsign(nu,5)+5	             	! to all upstream nodes
c           i=nsign(nu,j2)		

c        matrixvehicle4(phase2,jd)=matrixvehicle4(phase2,jd)+
c     +  matrixvehicle2(phase2,jd,i)	
		
c        enddo
c       enddo	   
c      enddo
	  
      matrixvehicle1=matrixvehicle2

c      if(nodenumber.eq.120)then
c        pause
c      endif
	  
      return
      end
