      subroutine RT_ROPAC_2(nodenumber,ll)
c     + nu_mv,nu_ph1,time_now,nu_ve,tii2,narcs,noofnodes,)
C     + vtmp,s,SatFlowRate,cma,cma_time
C     + ,movement,nodenum,kgpoint,llink,nsign,vehicle_queue,cmalink,green) 
c --
c -- This subroutine calculates the green time for each approach, if the intersection has seudo-DynaROPAC signal control.
c --
c -- This subroutine is called from intersection_control.
c -- This subroutine calls other subroutines.
c --
c -- INPUT :
c --  nodenumber : the intersection number.
c --  t : the start of the current simulation interval
c -- OUTPUT :
c --  green times for each approach and each movement.

      use muc_mod

      real TTropac,T1ropac,T2ropac,t_now,t_act
      real T1max,T2max,TTmax,Minimum_time,g,t_old
c      real time_now,tii2	  
      integer KKropac,K1ropac,K2ropac,SSropac,error,pha,pa,nw
      integer nip,nodenumber,mgg,lnum,m,narcs,contador,h,nf,ll
      integer phase_optima,n11,n2,i,linktime,nuu,iphaseRT,yflg
      integer reset,old_iphaseRT,maker_ok
c      integer nu_mv,nu_ph1,nu_ve,narcs,noofnodes,phase
      integer, DIMENSION(1:2,10)::phasevehicle
      integer, DIMENSION(1:10)::vectorphase
      integer, DIMENSION(1:10)::vectortime
      real, DIMENSION(1:10)::cma_time_2
      INTEGER,allocatable::nsign_tmp(:,:)
	  
      allocate(nsign_tmp(noofnodes*nu_mv,14),stat=error)
      if(error.ne.0) then
      write(911,*)'allcoate nsign_tmp error-insufficient memory'
      stop
      endif
      nsign_tmp(:,:)=0	 
	  
      allocate(contveh_que2(2,nu_ph1,noofarcs),stat=error)
      if(error.ne.0)then
      write(911,*) 'allocate contveh_que error - insufficient memory'
       stop
      endif	  
	  
c      integer,allocatable::Kqueue(:,:)
c      integer,allocatable::matrixgreen(:,:)
c      integer,allocatable::mgreen(:,:)
c      integer,allocatable::cma_osco(:)
c      integer,allocatable::cma_osco2(:)
c      integer,allocatable::contveh_que(:,:,:)

C      integer nsign(noofnodes*nu_mv,14),vehicle_queue(narcs)
C      integer cmalink(nu_ph1),green(narcs,nu_mv),kgpoint(noofnodes+1)
C      integer movement(narcs,nu_ph1,nu_mv),nodenum(noofnodes)
C      integer llink(narcs,nu_mv+1)
C      real vtmp(narcs),s(narcs),SatFlowRate(narcs),cma(nu_ph1)
C      real cma_time(nu_ph1)
      phase_optima=0
      reset=0
      narcs=noofarcs
      vectorphase(:)=0
      vectortime(:)=0
      phasevehicle(:,:)=0
      Minimum_time=0
c      print *,'Alex_DYROPAC'
 
      allocate(Kqueue(narcs,7),stat=error)
      if(error.ne.0)then
      write(911,*) 'allocate Kqueue error - insufficient memory'
       stop
      endif
      Kqueue(:,:)=0
c      print *,'Alex_DYROPAC_1',nu_ph1,narcs
	  
      allocate(contveh_que(2,nu_ph1,narcs),stat=error)
      if(error.ne.0)then
      write(911,*) 'allocate contveh_que error - insufficient memory'
       stop
      endif
      contveh_que(:,:,:)=0	  

c      print *,'Alex_DYROPAC_1A',nodenumber
c      print *,'Alex_DYROPAC_1B',nodenumber,tii	  
c --
c -- nip : the controlled intersection
c -- n11 : the starting phase for the current intersection
c -- n2 : the ending phase for the current intersection
c --
      nip=nodenum(nodenumber)
      n11=kgpoint(nip)
      n2=kgpoint(nip+1)-1
c --
C      print *,'Alex_DYROPAC_2',nip,n11,n2
      t_now=time_now-tii*60
c --
c --  t_now is the start of the current simulation interval
c -- t_act is the end of the current simulation interval.
c --
      t_act=time_now  
      t_old=t_act
c -- 
      TTropac=0
      Link_lenght=1000000
      T1ropac=0
      T2ropac=0
      T1max=0
      T2max=0
      TTmax=0	  

c -- pha is a varibale to keep track of the current phase number.	  
c -- Note : the difference between n11, n2 and phase is the following
c -- n11 and n2 are calculated by sorting all the phases in the network.
c -- n11 and n2 define the starting and ending phases for the current node.
c -- The "pha" is just the phase number, provided in the control input file, at the current node.
c      print *,n11,n2,1   

      do 400 nuu=n11,n2
         pha=nsign(nuu,1)
c	 print *,'Alex150'
        do 500 j=6,5+nsign(nuu,5)           ! to all upstream nodes
            linktime=nsign(nuu,j)           ! Upstream links
            if(npar(linktime).gt.0)then 
       if(npar(linktime).gt.MaxLinkVeh)then
         print *, 'error' 
       endif			
c	print *,linktime,nuu,2
c      print *,'Alex21',linktime,nuu,pha,nu_ph1,narcs
c--
c -- use RT_GET_VEH_OPAC to count the vehicles in queue and in the rest of the link 
c --
c      print *,'before RT_GET_VEH_OPAC'
      if(nodenumber.eq.120)then
	  
c      print *,'before RT_GET_VEH_OPAC',linktime,nuu,pha

      endif
	  
      call RT_GET_VEH_OPAC(linktime,nuu,pha,nodenumber)
c	  ,nu_ph1,narcs,contveh_que)
c      print *,'after RT_GET_VEH_OPAC'	  
c     + icurrnt,nu_ve	  )
c      print *,'Alex21b'
      phasevehicle(2,pha)=phasevehicle(2,pha)+
     +contveh_que(2,pha,linktime)-contveh_que(1,pha,linktime)
      phasevehicle(1,pha)=phasevehicle(1,pha)+
     +						contveh_que(1,pha,linktime)

c	print *,'Alex200'
c	print *,nuu,n11,nuu-n11,linktime
c	print *,5,SatFlowRate(linktime)
c --
c -- use the counts of vehicles in link and queue to set the lenght of the projection horizon
c -- here SatFlowRate is in veh/sec and vtmp seems to be in miles / min
c --  vtmp(i): speed on the queue-free length of link i.
c --
         if(vtmp(linktime).gt.0)then
c        if(s(linktime)/vtmp(linktime)*60.le.Link_lenght)then

      Link_lenght=s(linktime)/vtmp(linktime)*60
      T1ropac=contveh_que(1,nuu-n11+1,linktime)/SatFlowRate(linktime)
	  
       if(contveh_que(2,nuu-n11+1,linktime)-
     +     contveh_que(1,nuu-n11+1,linktime).gt.0)then	  
           T2ropac=link_lenght-T1ropac
       endif
	   
      if(T2ropac.lt.0) T2ropac=0
	  
      TTropac=T2ropac+T1ropac
	  
c				if (TTropac.lt.(contveh_que(1,nuu-n11+1,linktime)
c	+				/sat(linktime)+link_lenght)) then
     		  
c --  ctmp = vehiculos en el link sin incluir la cola, dividido por la longuitud
c --  libre del link.	
c --  s = longitud en millas del link completo. 

c			T2ropac=link_lenght
c			T1ropac=contveh_que(1,nuu-n11+1,linktime)/sat(linktime)
c			TTropac=T1ropac+T2ropac 
c				endif   
c       endif

      elseif(TTropac.lt.(contveh_que(1,nuu-n11+1,linktime)
     +									/SatFlowRate(linktime)))then
      T1ropac=contveh_que(1,nuu-n11+1,linktime)/SatFlowRate(linktime)
      TTropac=T1ropac
      endif
	  
      if((T1ropac).gt.(T1max))then 

        T1max=T1ropac
        T2max=T2ropac
        TTmax=TTropac
		
      endif		

        if(contveh_que(1,nuu-n11+1,linktime)/SatFlowRate(linktime).lt.
     + 														tii*60)then
           Kqueue(linktime,pha)=1
        else
           Kqueue(linktime,pha)=nint(contveh_que(1,nuu-n11+1,linktime)/
     +					SatFlowRate(linktime)/(tii*60))+1
         if(Kqueue(linktime,pha).gt.8) Kqueue(linktime,pha)=8	  
        endif	 	  

c        if(nodenumber.eq.120)then			
c          print *,Kqueue(linktime,pha),linktime,pha	  
c        endif

          endif
500      enddo
400   enddo

       T1ropac=T1max
       T2ropac=T2max
       TTropac=TTmax
			  
c      if(TTropac.le.Minimum_time)then
c      call ropac_3(nodenumber)
c      goto 5555
c      endif 

c     	write(1000,*) t_now,TTropac

      if(T1ropac.lt.tii*60)then 
       K1ropac=1
      else 
       K1ropac=nint(T1ropac/(tii*60))+1
      endif     
      if(T2ropac.lt.tii*60)then 
      K2ropac=1
      else 
      K2ropac=nint(T2ropac/(tii*60))+1
      endif
      KKropac=K1ropac+K2ropac  

      if(KKropac.gt.5) KKropac=5	  

c      print *,'node=',nodenumber,'Nosco = ',KKropac	  

      allocate(matrixgreen(n2-n11+1,KKropac),stat=error)
      if(error.ne.0) print *,'error'
      matrixgreen(:,:)=0

      allocate(mgreen(n2-n11+1,KKropac),stat=error)
      if(error.ne.0) print *,'error'
      mgreen(:,:)=0

c -------------------------------------------------------------------------------
      do 601 i=n11,n2						! to all phases
         phase=nsign(i,1)
         cma(phase)=0.0
       do 701 j=6,nsign(i,5)+5				! to all upstream nodes
              linktmp=nsign(i,j)			! Upstream links
	     if(cma(phase).le.vehicle_queue(linktmp))then
	          cma(phase)=vehicle_queue(linktmp)
              cmalink(phase)=linktmp
           endif
701     continue
601   continue
c	write(2,*) 'veh upstream, veh queue, time actuate, time opac'
c	write(2,24) (phasevehicle(2,i), i=1, n2-n11+1)
c	write(2,24) (phasevehicle(1,i), i=1, n2-n11+1) 
c --
c -- determine the extension of the green time by calculating the required
c -- time to discharge the maximum queue according to the saturation flow rate.
c --
      do 901 i=n11,n2
      phase=nsign(i,1)
      cma_time(phase)=cma(phase)/SatFlowRate(cmalink(phase))
901   continue

c	write(2,24) (cma_time(i), i=1, n2-n11+1)
c------------------------------------------------------------------------
      do ik=nsign(n11,1),nsign(n2,1)
        vectorphase(ik)=ik
        vectortime(ik)=nsign(ik+n11-1,13)		! end of green time
      enddo

c -- sort from smallest to largest . . .
	  
      do ik=nsign(n11,1),nsign(n2,1)-1
       do il=ik+1,nsign(n2,1)
         if(vectortime(ik).gt.vectortime(il))then
				mayort=vectortime(ik)
				mayorp=vectorphase(ik)
				vectortime(ik)=vectortime(il)
				vectorphase(ik)=vectorphase(il)
     			vectortime(il)=mayort
				vectorphase(il)=mayorp
         endif
       enddo
      enddo

      iphaseRT=0
      do ik=nsign(n11,1),nsign(n2,1)
         if(t_now.le.vectortime(ik))then 
               iphaseRT=vectorphase(ik)+n11-1
             goto 2000
         endif
      enddo
2000  continue
      iphase2=iphaseRT
	  
      if(iphaseRT.eq.0.or.iphaseRT.lt.n11.or.oiphaseRT.gt.n2)then	   
       print *, 'problem_4_1',iphaseRT,n11,n2
       do ik=nsign(n11,1),nsign(n2,1)
        print *, t_now,vectortime(ik),nsign(ik+n11-1,13),ik,n11,n2,
     +	nodenumber,ll 	
       enddo
        pause
      endif	  

c --
c      print *,'Alex24',iphaseRT
c      if(nodenumber.eq.5) print *,'before_RT_OSCO',KKropac

       iflg=0
       xflg=0
	   
        if(nodenumber.eq.120)then		   
      open(unit=1,file='matrix.dat',STATUS='UNKNOWN')	
        endif
	  
      call RT_OSCO(KKropac,n11,n2,t_now,nu_ph1,narcs,iphaseRT,
     + nodenumber,ll)
c	  Kqueue,matrixgreen,mgreen,
c     +	  nsign,noofnodes,nu_mv,tii,contveh_que)
c      print *,'after RT_OSCO' 
c      print *,'Alex25'

      phase=nsign(iphaseRT,1)
c --  
c     do 900 i=n11,n2
c     phase=nsign(i,1)
c	SSropac=0
c	FFropac=i-n11+1

c	do j=1,KKropac
c	if (mgreen(phase,1).gt.0) then
c	if (mgreen(phase,j).eq.0) exit
c	SSropac=SSropac+mgreen(phase,j)
c	endif
c	enddo
      cma_time(:)=0
c	cma_time(phase)=FLOAT(SSropac)*tii*60
      cma_time(phase)=mgreen(phase,1)*tii*60
  
c - -  cma_time(phase)=cma(phase)/sat(cmalink(phase))		            ! VRi,T/Si
c900   continue
c - -	
c      print *,'after RT_OSCO_1' 	
c	WRITE(2,*) phase	
c - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - 
      allocate(cma_osco2((n2-n11+1)*KKropac),stat=error)
      if(error.ne.0) print *,'error'
      cma_osco2(:)=0
	  
      nf=n2-n11+1
      pa=1
      do i=1,KKropac
       do j=1,nf
c         print *, 'alexmgreen',mgreen(j,i)	   
            if((mgreen(j,i).eq.1).and.(cma_osco2(1).eq.0))then
              cma_osco2(pa)=j
              pa=pa+1
            elseif(pa.gt.1)then
              if((mgreen(j,i).eq.1).and.
     +					(mgreen(cma_osco2(pa-1),i).eq.0))then
                cma_osco2(pa)=j
                pa=pa+1
              endif
           endif
       enddo
      enddo

	  
	  
      if(phase.eq.cma_osco2(1))then
      	  cma_time(phase)=tii*60
          phase_optima=cma_osco2(1)	
      else	  
         if((t_now-nsign(iphaseRT,12)).ge.nsign(iphaseRT,3))then
             t=t_now+nsign(iphaseRT,4)	
             xflg=1	
			 
         else
         if((nsign(iphaseRT,3)+nsign(iphaseRT,12)).le.t_act)then
		 
           if(nsign(iphaseRT,12).lt.t_now)then		 
      		 t=nsign(iphaseRT,3)+nsign(iphaseRT,12)+nsign(iphaseRT,4)
           else
      		 t=nsign(iphaseRT,14)
             old_iphaseRT=iphaseRT
      if(past_phase(nodenumber).ne.cma_osco2(1).and.(cma_osco2(1).ne.0))
     +	  then 
	     iphaseRT=cma_osco2(1)+n11-1
      elseif(past_phase(nodenumber).ne.cma_osco2(2).and.
     +	  (cma_osco2(2).ne.0)) then 
	     iphaseRT=cma_osco2(2)+n11-1
      elseif(past_phase(nodenumber).ne.cma_osco2(3).and.
     +	  (cma_osco2(3).ne.0)) then 
	     iphaseRT=cma_osco2(3)+n11-1
      endif	 

      if(iphaseRT.gt.nsign(n2,1)+n11-1) iphaseRT=iphaseRT-1
      if(iphaseRT.eq.past_phase(nodenumber)+n11-1) iphaseRT=iphaseRT+1
      if(iphaseRT.gt.nsign(n2,1)+n11-1) iphaseRT=iphaseRT-1
      if(iphaseRT.eq.past_phase(nodenumber)+n11-1) iphaseRT=iphaseRT-1
      if(iphaseRT.lt.nsign(n11,1)+n11-1) iphaseRT=iphaseRT+1	

       if(iphaseRT.lt.n11.or.oiphaseRT.gt.n2)then
      print *,'problem_42',iphaseRT,n11,n2,nsign(n11,1),nsign(n2,1)
         pause
       endif		  
	  
         phase=nsign(iphaseRT,1)
		 
       if(old_iphaseRT.lt.n11.or.old_iphaseRT.gt.n2)then
         print *, 'problem_3',old_iphaseRT,n11,n2
         pause
       endif
	   
         nsign(iphaseRT,12)=nsign(old_iphaseRT,12)	  
           endif		   
             xflg=1		
	     endif
      endif
c             t=nsign(iphaseRT,13)+nsign(iphaseRT,4)
      if(xflg.eq.1)then	

       if(iphaseRT.lt.n11.or.iphaseRT.gt.n2)then
        print *,'problem_4',iphaseRT,n11,n2,nsign(n11,1),nsign(n2,1)
        pause
       endif	  
	  
         nsign(iphaseRT,13)=t-nsign(iphaseRT,4)
         nsign(iphaseRT,14)=t
		 
    		 iflg=1
			 
      phase_optima=cma_osco2(1)			 
      if(phase_optima.eq.0) phase_optima=cma_osco2(2)
      if(phase_optima.eq.0) phase_optima=cma_osco2(3)
      if(phase_optima.eq.0) phase_optima=cma_osco2(4)	  
      if(phase_optima.eq.0) phase_optima=phase+1
      if(phase_optima.gt.nsign(n2,1)) phase_optima=phase-1
      if(phase_optima.eq.phase) phase_optima=phase+1
      if(phase_optima.gt.nsign(n2,1)) phase_optima=phase-1	  
      if(phase_optima.lt.nsign(n11,1)) phase_optima=phase+1

        if(phase_optima.eq.0)then
       print *,'problem_1'		
       print *,phase,cma_osco2(2),cma_osco2(3),cma_osco2(4)
       pause
        endif		  
	  
         do nw=phase_optima+n11-1,n2
		 
      if(nw.eq.0)then 
           print *,noofnodes*nu_mv,nw,phase_optima,n11,n2
     +		   ,nodenumber,delaycont,mindelay
      do i=1,KKropac
       do j=1,nf   
            print *, mgreen(j,i),matrixgreen(j,i)
       enddo
      enddo
      endif
	  
           if(iphaseRT.ne.nw.and.nw.ge.n11.and.nw.le.n2)then			
	       nsign(nw,12)=t
           nsign(nw,13)=t+nsign(nw,3)
	       nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
           t=nsign(nw,14)
           endif
         enddo

         do nw=n11,phase_optima+n11-1-1
           if(iphaseRT.ne.nw.and.nw.ge.n11.and.nw.le.n2)then	
           nsign(nw,12)=t
           nsign(nw,13)=t+nsign(nw,3)
           nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
           t=nsign(nw,14)
           endif
         enddo
		 
c         iphaseRT=cma_osco2(1)+n11-1
c         phase=nsign(iphaseRT,1)		 	 
            goto 550
         endif
      endif
C      print *,'after RT_OSCO_2',n11,n2 
c	write(2,24) (cma_time(i), i=1, n2-n11+1)

c	  write(1,*) 'orden'
c	  write(2,14) (cma_osco2(h), h=1, nf)

c - - - - - - - - - - - - - - - - - -  - - - - - - - - - - - - - - -
c --  iphase is an index to keep track of the active phase number. 

c --
c	call get_iphase_osco(n11,n2,KKropac,t_now)
c	call get_iphase_ropac(n11,n2,KKropac,t_now)
c --
c --  gtmp is a temprary variable to keep the assigned green time for the current phase.
c --
c --  NOTE : nsign(iphase,13) defines the end of green for phase iphase.
c --        In this case, the value for nsign(iphase,13) is dynamically
c --        allocted (i.e. it is not a predefined value).
c --
       gtmp=cma_time(nsign(iphaseRT,1))
	   
      if(t_now+gtmp.ge.nsign(iphaseRT,13))then
c -- 
c --  check if gmax is exceeded.  
c --
         if((nsign(iphaseRT,13)+gtmp-nsign(iphaseRT,12))
     +										.ge.nsign(iphaseRT,2))then
            gtmp=nsign(iphaseRT,2)+nsign(iphaseRT,12)-nsign(iphaseRT,13)
            iflg=1			
c         print *,'iflg=1, gmax',gtmp			
         endif
c --
c -- check for minimum green
c --
         if((nsign(iphaseRT,13)+gtmp-nsign(iphaseRT,12))
     +										.lt.nsign(iphaseRT,3))then
            gtmp=nsign(iphaseRT,3)+nsign(iphaseRT,12)-nsign(iphaseRT,13)
         endif
c --
c -- redefine the start and end of green time for all consequent phases
c -- according to the allocated green time to the current phase (iphase).
c --
c         nsign(iphase,13)=nsign(iphase,13)+gtmp
c         nsign(iphase,14)=nsign(iphase,14)+gtmp
c         do ik=iphase+1,n2
c            nsign(ik,12)=nsign(ik,12)+gtmp
c            nsign(ik,13)=nsign(ik,13)+gtmp
c            nsign(ik,14)=nsign(ik,14)+gtmp
c         end do
       if(gtmp.gt.0)then
         do ik=n11,n2
           if(nsign(ik,12).ge.nsign(iphaseRT,14))then
               if(iphaseRT.ne.ik.and.ik.ge.n11.and.ik.le.n2)then
                    nsign(ik,12)=nsign(ik,12)+gtmp 
                    nsign(ik,13)=nsign(ik,13)+gtmp
                    nsign(ik,14)=nsign(ik,14)+gtmp
               endif
            endif
         enddo
         nsign(iphaseRT,13)=nsign(iphaseRT,13)+gtmp
         nsign(iphaseRT,14)=nsign(iphaseRT,14)+gtmp
       endif
      endif
c --
       
c --
c -- iflg is a flag to check if this is the end of a cycle
c -- iflg=1, if this is the end of a cycle and 0 otherwise.
c --
c      print *,'after RT_OSCO_3' 
c      iflg=0

550    if(iflg.eq.1.and.xflg.eq.0)then 
          if(t_act.ge.nsign(iphaseRT,14))then
             t_act=nsign(iphaseRT,14)
             t_old=t_act
          endif

C	elseif (t_act.ge.nsign(vectorphase(nsign(n2,1))+n11-1,13)) then 
C            iflg=1
c		   xflg=1
c          if (t_act.ge.nsign(vectorphase(nsign(n2,1))+n11-1,14)) then
c             t_act=nsign(vectorphase(nsign(n2,1))+n11-1,14)
c             t_old=t_act
c          endif
      endif
c	endif
      g=0
      g2=0
      cma_time_2(:)=0

c      print *,'after RT_OSCO_4' 
c --
        contador=0
        yflg=0	   
		
        if(nodenumber.eq.120)then	
		
c       do j=1,nf
c         print *,(mgreen(j,i),i=1,KKropac),'*',
c     +		 (matrixvehicle4(j,i),i=1,KKropac)
c       enddo
	   
c         print *,'timing data:',mindelay,gtmp	
	     write(1,*) 'minimum delay =',mindelay	
		 
       do j=1,nf
         write(1,*) (mgreen(j,i),i=1,KKropac),'*',
     +		 (matrixvehicle4(j,i),i=1,KKropac)
       enddo			
			
        close(1)	
		
        endif	   
		
1300   do 100 nuu=n11,n2
       iphaseRT=nsign(nuu,1)
c -- 
c -- g is a variable to keep the green time (le) value for the current phase
c --

c --  t_now is the start of the current simulation interval
c -- t_act is the end of the current simulation interval.	   
	   
       g=0
       if(t_now.ge.nsign(nuu,12).and.t_act.le.nsign(nuu,13))then
                 g=t_act-t_now
c	 write(2,*) 'lili 1'
       elseif(t_act.gt.nsign(nuu,13).and.t_now.le.nsign(nuu,13))then
                 g=nsign(nuu,13)-t_now
c      if((iflg.eq.0).and.(xflg.eq.0).and.(iphaseRT.eq.iphase2))then
cc         if(g.lt.6)then
c            iflg=1

cc         print *,'iflg=1, t_act.gt.nsign(nuu,13)_1',g						
c          if(t_act.ge.nsign(nuu,14))then
c             t_act=nsign(nuu,14)
c             t_old=t_act
c             xflg=1			 
c          endif
cc         endif
c      endif
cc	 write(2,*) 'lili 2'
       elseif(t_act.ge.nsign(nuu,12).and.t_now.lt.nsign(nuu,12))then
                 g=t_act-nsign(nuu,12)
c	 write(2,*) 'lili 3'
      elseif(t_act.gt.nsign(nuu,13).and.t_now.lt.nsign(nuu,12))then
			   g=nsign(nuu,13)-nsign(nuu,12)
c      if((iflg.eq.0).and.(xflg.eq.0).and.(iphaseRT.eq.iphase2))then
cc        if(g.lt.6)then
c            iflg=1
cc         print *,'iflg=1, t_act.gt.nsign(nuu,13)_2',g				
c          if(t_act.ge.nsign(nuu,14))then
c             t_act=nsign(nuu,14)
c             t_old=t_act
c             xflg=1			 
c          endif
cc        endif
c      endif
c	 write(2,*) 'lili 4'
      endif

c -- reset because phases are updated before the green time is actully assigned
	  
      if(g.eq.0.and.iphaseRT.eq.phase_optima.and.yflg.eq.1.and.
     +   t_act.le.nsign_tmp(phase+n11-1,13))then
        reset=1
      endif	  
	  
      if(g.ne.0)then
        g2=g2+1
      endif
c	  FFropac=nuu-n11+1
c	if (iphase.eq.nq) then
        cma_time_2(iphaseRT)=g
c	endif		            !
c --
c -- allocate the green for each movement in the current phase (iphase)
c --
c         print *, 'in_ROPAC'
	  
             do 201 m=6,5+nsign(nuu,5)
C      print *, 'after_in_ROPAC0'	 			 
		     lnum=nsign(nuu,m)
C      print *, 'after_in_ROPAC1',lnum,nu_mv	 			 
		     do 200 mgg=1,llink(lnum,nu_mv+1)
c        if(nodenumber.eq.5)then					 
c      print *, 'in_ROPAC2',mgg,llink(lnum,nu_mv+1),lnum,nu_mv,nuu,n11,
c     +	  green(lnum,mgg)
c        endif	 
                 if(nuu.gt.n11)then
C      print *, 'after_in_ROPAC3'	 				 
                   if(green(lnum,mgg).gt.0) goto 200
                 endif
c                  green(lnum,mg)=g*movement(lnum,nuu,mg)
C      print *, 'after_in_ROPAC4'	 
                  green(lnum,mgg)=g*movement(lnum,iphaseRT,mgg)
				  
        if(nodenumber.eq.120)then	

      if(green(lnum,mgg).eq.0)then	
       contador=contador+1	  
      endif		
	  

c	 ,phase,cma_time(phase)
c     + ,cma_osco2(1),g,mgreen(iphaseRT,1),iphaseRT
c     + ,matrixgreen(iphaseRT,1)	 

c      print *, green(lnum,mgg),vehicle_queue(lnum),lnum,mgg,ll
c     +	  ,contveh_que(1,iphaseRT,lnum)
c     + ,contveh_que(2,iphaseRT,lnum),phase_optima,cma_osco2(1),
c     + cma_osco2(2),cma_osco2(3),nsign(iphaseRT+n11-1,12),
c     + nsign(iphaseRT+n11-1,13),nsign(iphaseRT+n11-1,14),	 
c     + nsign(iphaseRT+n11-1,3),nsign(iphaseRT+n11-1,4)	
	 
        endif
		
	
		
c     +,mg,llink(lnum,nu_mv+1)	  
200    continue
c       IF(ll*6.ge.294) 
c     + write(1,*) (green(lnum,mgg), mgg=1,llink(lnum,nu_mv+1))
201   continue	
  
c      IF(ll*6.ge.294) 
c     + write(1,*)  nsign(nuu,12),nsign(nuu,13),nsign(nuu,14)
	  
100   continue
c      g=0
      g2=0
c --
c      IF(ll*6.ge.294)THEN
c      write(1,*) 'lista de phases'
c      write(1,*) cma_osco2(1),cma_osco2(2),cma_osco2(3),cma_osco2(4)
c      write(1,*) 'conteos'	  
c      write(1,*) phasevehicle(1,1),phasevehicle(1,2),phasevehicle(1,3)
c      write(1,*) phasevehicle(2,1),phasevehicle(2,2),phasevehicle(2,3)	
c      write(1,*) 'end conteos'	 	  
c      write(1,*) '********************************************'
c      write(1,*) 't_now=',t_now,'t_act=',t_act,nsign(phase+n11-1,12),
c     + nsign(phase+n11-1,13),nsign(phase+n11-1,14),'phase=',phase	  
 
c      write(1,*) 'optimal phase secuence',delaycont,mindelay
c      do i=1,nf
c      write(1,*) (mgreen(i,h), h=1,KKropac)
c      enddo	  
c      write(1,*) '____________________________________________'
c      ENDIF

c --
c      print *,'after RT_OSCO_5' 
c	write(2,24) (cma_time_2(i), i=1, n2-n11+1)
	      
c      print *, 'after_in_ROPAC_2'
	  
c	if (phase_optima.ne.phase) then
      contador=0
      if(iflg.eq.1.and.xflg.eq.0)then
	  
       nsign_tmp=nsign	  

       phase_optima=cma_osco2(1)

c --
c --  if this is the end of a cycle, then set the starting and ending
c --  times iassumming minimum greeen for all phases as initial value.
c --
c          t=nsign(nuu,14)
c		np=nuu+1
c	if (nuu.eq.n2) np=n11
c	if (np.eq.n11) goto 911
c         do nw=np,n2
c	     nsign(nw,12)=t
c           nsign(nw,13)=t+nsign(nw,3)
c	     nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
c           t=nsign(nw,14)
c          enddo
c911		do nv=n11,nuu
c	     nsign(nv,12)=t
c           nsign(nv,13)=t+nsign(nv,3)
c	     nsign(nv,14)=nsign(nv,13)+nsign(nv,4)
c           t=nsign(nv,14)
c          enddo

c	if ((phase_optima.ne.phase).and.(phase_optima.ne.0)) then

c         t=nsign(phase+n11-1,14)
c	do i=1,n2-n11+1
c	if (vectorphase(i).eq.phase_optima) il=i
c	exit
c	enddo
c        do ik=il,n2-n11+1
c	   nsign(vectorphase(ik)+n11-1,12)=t
c         nsign(vectorphase(ik)+n11-1,13)=t+nsign(vectorphase(ik)+n11-1,3)
c	   nsign(vectorphase(ik)+n11-1,14)=nsign(vectorphase(ik)+n11-1,13)+
c	+   nsign(vectorphase(ik)+n11-1,4)
c        t=nsign(vectorphase(ik)+n11-1,14)
c         enddo
c         t=nsign(vectorphase(n2-n11+1)+n11-1,14)
c         do ik=1,il-1
c	   nsign(vectorphase(ik)+n11-1,12)=t
c         nsign(vectorphase(ik)+n11-1,13)=t+nsign(vectorphase(ik)+n11-1,3)
c	   nsign(vectorphase(ik)+n11-1,14)=nsign(vectorphase(ik)+n11-1,13)+
c	+   nsign(vectorphase(ik)+n11-1,4)
c         t=nsign(vectorphase(ik)+n11-1,14)
c         enddo

c      print *,phase_optima,phase,cma_osco2(1),cma_osco2(2),
c     + cma_osco2(3),cma_osco2(4)
	 
c      if(phase_optima.eq.phase.or.phase_optima.eq.0)then
      if(phase_optima.eq.phase)then	  
         phase_optima=cma_osco2(2)
      if(phase_optima.eq.0) phase_optima=cma_osco2(3)
      if(phase_optima.eq.0) phase_optima=cma_osco2(4)
      if(phase_optima.eq.0) phase_optima=phase+1
      if(phase_optima.gt.nsign(n2,1)) phase_optima=phase-1
      if(phase_optima.eq.phase) phase_optima=phase+1
      if(phase_optima.gt.nsign(n2,1)) phase_optima=phase-1	
      if(phase_optima.lt.nsign(n11,1)) phase_optima=phase+1
	  
      endif

 
          t=nsign(phase+n11-1,14)
c          print *, 'checking_update',t,phase,phase_optima	 
		  
        if(phase_optima.eq.0)then
       print *,'problem_2'			
       print *,phase,cma_osco2(2),cma_osco2(3),cma_osco2(4)
        endif		
 		  

         do nw=phase_optima+n11-1,n2
		 
      if(nw.eq.0)then 
           print *,noofnodes*nu_mv,nw,phase_optima,n11,n2
     +		   ,nodenumber,delaycont,mindelay
      do i=1,KKropac
       do j=1,nf   
            print *, mgreen(j,i),matrixgreen(j,i)
       enddo
      enddo
      endif
			
	       nsign(nw,12)=t
           nsign(nw,13)=t+nsign(nw,3)
	       nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
           t=nsign(nw,14)
         enddo

         do nw=n11,phase_optima+n11-1-1
           nsign(nw,12)=t
           nsign(nw,13)=t+nsign(nw,3)
           nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
           t=nsign(nw,14)
         enddo

c          t=nsign(phase+n11-1,14)
c         do nw=phase_optima+n11-1-1,n11,-1
c	     nsign(nw,14)=t
c           nsign(nw,13)=t-nsign(nw,4)
c	     nsign(nw,12)=nsign(nw,13)-nsign(nw,3)
c           t=nsign(nw,12)
c         enddo

c	else

c        t=nsign(n2,14)
c         do nw=n11,n2
c	     nsign(nw,12)=t
c           nsign(nw,13)=t+nsign(nw,3)
c	     nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
c           t=nsign(nw,14)
c         enddo
c	endif
c --
c --  Reset iflg, t_act and t_now
c --
        iflg=0
        yflg=1
		
c        if(xflg.eq.0)then
c         print *,'special_case'
c--         t_old=nsign(iphase2,14)
c        endif
		
        t_act=t_now+tii*60
        t_now=t_old           
c --
c -- if iflg=1, this means that the green time has been allocated for
c -- the last phase for the current intersection and there may exist some
c -- green time to be allocated to the first phase in the next cycle.
c -- So, return back and calculate the possible green for all phases.
c --
        goto 1300
		
c      pause
	  
      endif
c      print *,'after RT_OSCO_6' 
c	allocate (cma_osco(n2-n11+1),stat=error)
c  	if(error.ne.0) print *,'error'
c	cma_osco(:)=0
c
c	nf=n2-n11+1
c	pa=1
c	do i=1,KKropac
c		do j=1,nf
c			if ((mgreen(j,i).eq.1).and.(cma_osco(1).eq.0)) then
c			 cma_osco(pa)=j
c			 pa=pa+1
c			elseif ((mgreen(j,i).eq.1).and.
c	+						(mgreen(cma_osco(pa-1),i).eq.0)) then
c			 cma_osco(pa)=j
c			 pa=pa+1
c			endif
c		enddo
c	  enddo
c
c      iphase=0
c      do ik=n11,n2
c         if(t_now.le.nsign(ik,13)) then 
c               iphase=ik
c             goto 2002
c         endif
c      end do
c2002  continue
c
c	 if ((nsign(iphase,1).ne.cma_osco(2))
c	+							.and.(mgreen(phase,2).eq.0)) then
c
c	 if (cma_osco(2)-nsign(iphase,1).lt.0) then
c	 qq=cma_osco(2)-nsign(iphase,1)
c	 X=1
c	 else
c	 qq=nsign(iphase,1)-cma_osco(2)
c   	X=-1
c   	endif
c	 if (X.eq.1) then
c        t=nsign(nq,14)
c
c         do nw=iphase+qq,n2
c	     nsign(nw,12)=t
c           nsign(nw,13)=t+nsign(nw,3)
c	     nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
c           t=nsign(nw,14)
c         enddo
c         t=nsign(nq,14)
c	   nv=cma_osco(2)-1+n11-1
c         do nw=n11,iphase+qq-1
c	     nsign(nv,14)=t
c           nsign(nw,13)=t-nsign(nw,4)
c	     nsign(nw,12)=nsign(nw,13)-nsign(nw,3)
c           t=nsign(nw,12)
c	     nv=nv-1
c         enddo
c	 else
c		t=nsign(nq,14)
c
c         do nw=cma_osco(2)+n11-1,n2
c	     nsign(nw,12)=t
c           nsign(nw,13)=t+nsign(nw,3)
c	     nsign(nw,14)=nsign(nw,13)+nsign(nw,4)
c           t=nsign(nw,14)
c         enddo
c         t=nsign(nq,14)
c	   nv=cma_osco(2)-1+n11-1
c         do nw=n11,iphase+qq-1
c	     nsign(nv,14)=t
c           nsign(nw,13)=t-nsign(nw,4)
c	     nsign(nw,12)=nsign(nw,13)-nsign(nw,3)
c           t=nsign(nw,12)
c	     nv=nv-1
c         enddo
c
c	 endif

24    format(10f7.1)
14    format(10i7)
c        deallocate (cma_osco,stat=error)
      if(allocated(matrixgreen)) deallocate(matrixgreen,stat=error)
c      print *,'after RT_OSCO_61' 	   
      if(allocated(mgreen)) deallocate(mgreen,stat=error)
c      print *,'after RT_OSCO_62' 	   
      if(allocated(cma_osco2)) deallocate(cma_osco2,stat=error)
      if(allocated(matrixvehicle4)) 
     +	  deallocate(matrixvehicle4,stat=error)
c      print *,'after RT_OSCO_63' 	   
5555  continue
c      print *,'after RT_OSCO_7' 
       deallocate(Kqueue,stat=error)
       deallocate(contveh_que,stat=error)
c      print *,'after RT_OSCO_8' 	   
c			t12=nsign(nw,12)
c			t13=nsign(nw,13)
c			t14=nsign(nw,14)
c			nv=phase_optima+n11-1
c			nsign(nw,12)=nsign(nv,12)
c			nsign(nw,13)=nsign(nv,13)
c			nsign(nw,14)=nsign(nv,14)
c			nsign(nv,12)=t12
c			nsign(nv,13)=t13
c			nsign(nv,14)=t14

      if(reset.eq.1) nsign=nsign_tmp
      deallocate(nsign_tmp)
      deallocate(contveh_que2)
	  
      past_phase(nodenumber)=phase	

      return
      end
