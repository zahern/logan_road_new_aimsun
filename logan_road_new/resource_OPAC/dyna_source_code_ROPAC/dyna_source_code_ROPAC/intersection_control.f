      subroutine intersection_control(ll)
c --       
c -- This is the main subroutine for the signal control calculations.
c -- It checks the type of control at each intersection and calls
c -- the appropriate subroutine to calculate the green times.
c --
c -- This subroutine is called from loop every simulation interval.
c -- This subroutine calls the following subroutines
c --      1. no_control 
c --      2. yield_control
c --      3. stop_control
c --      4. pretimed_control
c --  and 5. actuated_control
c --
c -- INPUT : 
c --
c -- OUTPUT :
c --   No output
c --
      use muc_mod
      integer iphase,mg,nu,n1,n2,m,ll	  
c --
c -- Initialize the green times for each link and each movement before 
c -- calculating the green times for the current simulation interval.
c --
      do i=1,noofarcs
       do j=1,nu_mv
          green(i,j)=0.0
       enddo
      enddo
c --
c -- Check the control type at each intersection and call the corresponding subroutine.
c --

!      do 10 i=1,noofnodes
      do 10 i=1,noofnodes_org

      if(node(i,2).eq.1)then
            call no_control(i)
      elseif(node(i,2).eq.2)then
            call yield_control(i)
      elseif(node(i,2).eq.3)then
            call stop_control(i)
      elseif(node(i,2).eq.4)then
            call pretimed_control(i)
      elseif(node(i,2).eq.5)then
c      if(i.eq.5) print *, 'Actuated'	  
            call actuated_control(i,ll)
      elseif(node(i,2).eq.6)then
            call stop_control(i)
      elseif(node(i,2).eq.9)then
c	        print *,'CAL_ROPAC',i,noofarcs,tii,nu_ph1

c      print *, 'before ROPAC'	

c      n1=kgpoint(i)
c      n2=kgpoint(i+1)-1
  
c      do 100 nu=n1,n2
c       iphase=nsign(nu,1)	  
c             do 200 m=6,5+nsign(nu,5)
c		     lnum=nsign(nu,m)
c		     do 200 mg=1,llink(lnum,nu_mv+1)
c                 if(nu.gt.n1)then
c                   if(green(lnum,mg).gt.0) goto 200
c                 endif 
c      print *, green(lnum,mg),movement(lnum,iphase,mg),lnum,iphase,mg
c200    continue
c100    continue

c      if(i.eq.5) print *, 'ROPAC'
c      if(i.eq.5) write(1,*), 'ROPAC'

c      print *, 'intersection =>',i
	  
       call RT_ROPAC_2(i,ll)
	   
c        if(i.eq.120)then
c         print *, 'new data'
c         pause	
c        endif
		
c	   ,noofarcs,nsign,noofnodes,nu_mv,nu_ph1,
c     + time_now,nu_ve,	
c     + vtmp,s,SatFlowRate,cma,vehicle_queue,cmalink,cma_time,green,
c     + movement,nodenum,kgpoint,llink,tii)
	 
c      print *, 'after ROPAC'	 	 
c      n1=kgpoint(i)
c      n2=kgpoint(i+1)-1
 
c      do 101 nu=n1,n2
c       iphase=nsign(nu,1)		  
c             do 201 m=6,5+nsign(nu,5)
c		     lnum=nsign(nu,m)
c		     do 201 mg=1,llink(lnum,nu_mv+1)
c                 if(nu.gt.n1)then
c                   if(green(lnum,mg).gt.0) goto 201
c                 endif 
c      print *, green(lnum,mg),movement(lnum,iphase,mg),lnum,iphase,mg
c201    continue
c101    continue	 
	 
      endif

10    continue

      return
      end
